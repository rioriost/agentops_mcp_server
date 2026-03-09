class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/aa/24/07d74deb0b820ecd420b03941071eab36e01b32e3848861a4bf93e48fb5c/agentops_mcp_server-0.5.2.tar.gz"
  sha256 "5a229aaeee43b75110ddee40716d4c22c96b3e77965d1e679e804c630a128a70"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
