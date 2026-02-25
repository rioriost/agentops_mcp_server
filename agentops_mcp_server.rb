class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/22/4e/5ff36d9c8f4779e543331267ce666c7d5ec55f60da3ca555d4457015663d/agentops_mcp_server-0.0.5.tar.gz"
  sha256 "e1752f646c71001fddb5246260811efc7150a828cc9275f9bd6f3aa31bd1c27a"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
