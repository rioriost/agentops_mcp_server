class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/bd/ab/4783fd569f826186f312fe78ede9c17d775272ed425a5c0b667351120148/agentops_mcp_server-0.0.10.tar.gz"
  sha256 "3ff7b40618c65c2c22fbccf5a35a1afca799635ddeac1d27a62a9efab01ad286"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
